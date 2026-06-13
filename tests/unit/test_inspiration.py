from datetime import datetime, timezone
from pathlib import Path

from autoresearch.inspiration import (
    HackerNewsSearchClient,
    HuggingFaceDatasetClient,
    InspirationItem,
    InspirationRefreshConfig,
    run_inspiration_refresh,
)
from autoresearch.literature.clients import RateLimiter


def test_huggingface_dataset_client_parses_public_dataset_rows() -> None:
    def fake_get(url, params, headers):
        assert url == "https://huggingface.co/api/datasets"
        assert params["search"] == "pendigits"
        assert headers is None
        return [
            {
                "id": "user/pendigits-demo",
                "downloads": 12,
                "likes": 3,
                "tags": ["tabular", "classification"],
            }
        ]

    client = HuggingFaceDatasetClient(
        json_get=fake_get,
        rate_limiter=RateLimiter(0),
    )

    items = client.search("pendigits", limit=1)

    assert len(items) == 1
    assert items[0].source == "huggingface_datasets"
    assert items[0].source_type == "dataset_signal"
    assert items[0].title == "user/pendigits-demo"
    assert items[0].url == "https://huggingface.co/datasets/user/pendigits-demo"
    assert items[0].score == 15
    assert "classification" in items[0].tags


def test_hacker_news_client_parses_story_rows() -> None:
    def fake_get(url, params, headers):
        assert url == "https://hn.algolia.com/api/v1/search"
        assert params["query"] == "research agents"
        assert params["tags"] == "story"
        assert headers is None
        return {
            "hits": [
                {
                    "title": "Show HN: Research agent benchmark",
                    "url": "https://example.com/research-agent",
                    "objectID": "123",
                    "points": 10,
                    "num_comments": 5,
                    "author": "builder",
                    "created_at": "2026-06-13T00:00:00Z",
                }
            ]
        }

    client = HackerNewsSearchClient(json_get=fake_get, rate_limiter=RateLimiter(0))

    items = client.search("research agents", limit=1)

    assert len(items) == 1
    assert items[0].source == "hacker_news"
    assert items[0].source_type == "forum_signal"
    assert items[0].score == 15
    assert items[0].author == "builder"


def test_run_inspiration_refresh_writes_obsidian_summary(tmp_path: Path) -> None:
    class FakeClient:
        source_id = "fake"
        source_type = "forum_signal"
        rate_limit_seconds = 0.0

        def search(self, query: str, *, limit: int = 5) -> list[InspirationItem]:
            assert limit == 1
            return [
                InspirationItem(
                    source=self.source_id,
                    source_type=self.source_type,
                    title=f"Signal for {query}",
                    url=f"https://example.com/{query.replace(' ', '-')}",
                    query=query,
                    summary="Community signal only.",
                    score=1.0,
                    retrieved_at=datetime.now(timezone.utc),
                )
            ]

    report = run_inspiration_refresh(
        vault_root=tmp_path,
        queries=("autonomous research datasets",),
        clients={"fake": FakeClient()},
        config=InspirationRefreshConfig(max_queries=1, max_results_per_source=1),
    )

    assert report.summary_path is not None
    assert report.summary_path.is_file()
    assert len(report.items) == 1
    markdown = report.summary_path.read_text(encoding="utf-8")
    assert "Do not cite these items as scholarly evidence" in markdown
    assert "forum_signal" in markdown


def test_run_inspiration_refresh_records_source_errors(tmp_path: Path) -> None:
    class FailingClient:
        source_id = "failing"
        source_type = "dataset_signal"
        rate_limit_seconds = 0.0

        def search(self, query: str, *, limit: int = 5) -> list[InspirationItem]:
            assert query == "agent datasets"
            assert limit == 1
            raise RuntimeError("source unavailable")

    report = run_inspiration_refresh(
        vault_root=tmp_path,
        queries=("agent datasets",),
        clients={"failing": FailingClient()},
        config=InspirationRefreshConfig(max_queries=1, max_results_per_source=1),
    )

    assert not report.items
    assert report.fetches[0].error == "RuntimeError: source unavailable"
