"""Non-scholarly inspiration discovery for data and community signals."""

from __future__ import annotations

import json
import ssl
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, cast

import certifi

from autoresearch.knowledge import (
    KnowledgeEntry,
    KnowledgeEntryType,
    KnowledgeZone,
    MarkdownKnowledgeStore,
)
from autoresearch.literature.clients import RateLimiter

JsonGet = Callable[[str, dict[str, str | int], Mapping[str, str] | None], object]


class InspirationSearchClient(Protocol):
    """Minimal client interface for inspiration sources."""

    source_id: str
    source_type: str
    rate_limit_seconds: float

    def search(self, query: str, *, limit: int = 5) -> list[InspirationItem]:
        """Return inspiration items for one query."""


@dataclass(frozen=True)
class InspirationItem:
    """One source-backed non-scholarly inspiration signal."""

    source: str
    source_type: str
    title: str
    url: str
    query: str
    summary: str
    score: float
    retrieved_at: datetime
    author: str | None = None
    created_at: str | None = None
    tags: tuple[str, ...] = ()
    metadata: Mapping[str, object] | None = None

    def to_json_dict(self) -> dict[str, object]:
        """Return a stable JSON-serialisable representation."""

        return {
            "source": self.source,
            "source_type": self.source_type,
            "title": self.title,
            "url": self.url,
            "query": self.query,
            "summary": self.summary,
            "score": self.score,
            "retrieved_at": self.retrieved_at.isoformat(),
            "author": self.author,
            "created_at": self.created_at,
            "tags": list(self.tags),
            "metadata": dict(self.metadata or {}),
        }


@dataclass(frozen=True)
class InspirationFetchRecord:
    """Provenance for one inspiration-source fetch."""

    source: str
    source_type: str
    query: str
    result_count: int
    rate_limit_seconds: float
    error: str | None = None

    def to_json_dict(self) -> dict[str, object]:
        """Return a stable JSON-serialisable representation."""

        return {
            "source": self.source,
            "source_type": self.source_type,
            "query": self.query,
            "result_count": self.result_count,
            "rate_limit_seconds": self.rate_limit_seconds,
            "error": self.error,
        }


@dataclass(frozen=True)
class InspirationRefreshConfig:
    """Configuration for broad inspiration discovery."""

    max_queries: int = 3
    max_results_per_source: int = 5
    seed_queries: tuple[str, ...] = ()


@dataclass(frozen=True)
class InspirationRefreshReport:
    """Result of one broad-source inspiration discovery run."""

    queries: tuple[str, ...]
    fetches: tuple[InspirationFetchRecord, ...]
    items: tuple[InspirationItem, ...]
    summary_path: Path | None

    def to_json_dict(self) -> dict[str, object]:
        """Return a stable JSON-serialisable representation."""

        return {
            "queries": list(self.queries),
            "fetches": [fetch.to_json_dict() for fetch in self.fetches],
            "items": [item.to_json_dict() for item in self.items],
            "summary_path": self.summary_path.as_posix() if self.summary_path else None,
        }


class HuggingFaceDatasetClient:
    """Search public Hugging Face datasets as possible data sources."""

    source_id = "huggingface_datasets"
    source_type = "dataset_signal"
    api_url = "https://huggingface.co/api/datasets"

    def __init__(
        self,
        *,
        json_get: JsonGet | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self.json_get = json_get or _urllib_get_json
        self.rate_limiter = rate_limiter or RateLimiter(1.0)
        self.rate_limit_seconds = self.rate_limiter.min_interval_seconds

    def search(self, query: str, *, limit: int = 5) -> list[InspirationItem]:
        self.rate_limiter.wait()
        payload = self.json_get(
            self.api_url,
            {"search": query, "limit": limit, "sort": "downloads", "direction": "-1"},
            None,
        )
        if not isinstance(payload, list):
            return []
        timestamp = datetime.now(timezone.utc)
        items: list[InspirationItem] = []
        for row in payload[:limit]:
            if not isinstance(row, dict):
                continue
            dataset_id = _string(row.get("id")) or _string(row.get("_id"))
            if not dataset_id:
                continue
            downloads = _number(row.get("downloads"))
            likes = _number(row.get("likes"))
            tags = tuple(str(tag) for tag in row.get("tags", []) if isinstance(tag, str))
            items.append(
                InspirationItem(
                    source=self.source_id,
                    source_type=self.source_type,
                    title=dataset_id,
                    url=f"https://huggingface.co/datasets/{dataset_id}",
                    query=query,
                    summary="Public Hugging Face dataset candidate; inspect the dataset card before use.",
                    score=downloads + likes,
                    retrieved_at=timestamp,
                    tags=tags,
                    metadata={
                        "downloads": downloads,
                        "likes": likes,
                        "private": bool(row.get("private", False)),
                        "gated": bool(row.get("gated", False)),
                    },
                )
            )
        return items


class GitHubRepositorySearchClient:
    """Search public GitHub repositories as code/ecosystem feasibility signals."""

    source_id = "github_repositories"
    source_type = "code_signal"
    api_url = "https://api.github.com/search/repositories"

    def __init__(
        self,
        *,
        json_get: JsonGet | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self.json_get = json_get or _urllib_get_json
        self.rate_limiter = rate_limiter or RateLimiter(1.0)
        self.rate_limit_seconds = self.rate_limiter.min_interval_seconds

    def search(self, query: str, *, limit: int = 5) -> list[InspirationItem]:
        self.rate_limiter.wait()
        payload = self.json_get(
            self.api_url,
            {
                "q": query,
                "sort": "stars",
                "order": "desc",
                "per_page": limit,
            },
            {
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        if not isinstance(payload, dict):
            return []
        rows = payload.get("items", [])
        if not isinstance(rows, list):
            return []
        timestamp = datetime.now(timezone.utc)
        items: list[InspirationItem] = []
        for row in rows[:limit]:
            if not isinstance(row, dict):
                continue
            full_name = _string(row.get("full_name"))
            url = _string(row.get("html_url"))
            if not full_name or not url:
                continue
            stars = _number(row.get("stargazers_count"))
            forks = _number(row.get("forks_count"))
            license_key = None
            license_row = row.get("license")
            if isinstance(license_row, dict):
                license_key = _string(license_row.get("key"))
            topics = tuple(str(topic) for topic in row.get("topics", []) if isinstance(topic, str))
            items.append(
                InspirationItem(
                    source=self.source_id,
                    source_type=self.source_type,
                    title=full_name,
                    url=url,
                    query=query,
                    summary=(
                        "Public GitHub repository signal; inspect license, maintenance, "
                        "and reproducibility before using it as implementation evidence."
                    ),
                    score=stars + forks,
                    retrieved_at=timestamp,
                    author=_string(row.get("owner", {}).get("login"))
                    if isinstance(row.get("owner"), dict)
                    else None,
                    created_at=_string(row.get("created_at")),
                    tags=topics,
                    metadata={
                        "stars": stars,
                        "forks": forks,
                        "language": _string(row.get("language")),
                        "license": license_key,
                        "archived": bool(row.get("archived", False)),
                        "disabled": bool(row.get("disabled", False)),
                    },
                )
            )
        return items


class HackerNewsSearchClient:
    """Search Hacker News stories as community/news inspiration signals."""

    source_id = "hacker_news"
    source_type = "forum_signal"
    api_url = "https://hn.algolia.com/api/v1/search"

    def __init__(
        self,
        *,
        json_get: JsonGet | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self.json_get = json_get or _urllib_get_json
        self.rate_limiter = rate_limiter or RateLimiter(1.0)
        self.rate_limit_seconds = self.rate_limiter.min_interval_seconds

    def search(self, query: str, *, limit: int = 5) -> list[InspirationItem]:
        self.rate_limiter.wait()
        payload = self.json_get(
            self.api_url,
            {"query": query, "tags": "story", "hitsPerPage": limit},
            None,
        )
        if not isinstance(payload, dict):
            return []
        rows = payload.get("hits", [])
        if not isinstance(rows, list):
            return []
        timestamp = datetime.now(timezone.utc)
        items: list[InspirationItem] = []
        for row in rows[:limit]:
            if not isinstance(row, dict):
                continue
            title = _string(row.get("title")) or _string(row.get("story_title"))
            object_id = _string(row.get("objectID"))
            if not title or not object_id:
                continue
            url = _string(row.get("url")) or f"https://news.ycombinator.com/item?id={object_id}"
            points = _number(row.get("points"))
            comments = _number(row.get("num_comments"))
            items.append(
                InspirationItem(
                    source=self.source_id,
                    source_type=self.source_type,
                    title=title,
                    url=url,
                    query=query,
                    summary="Community/news signal; use for inspiration only, not as scholarly evidence.",
                    score=points + comments,
                    retrieved_at=timestamp,
                    author=_string(row.get("author")),
                    created_at=_string(row.get("created_at")),
                    tags=("hacker-news",),
                    metadata={"points": points, "num_comments": comments, "object_id": object_id},
                )
            )
        return items


def run_inspiration_refresh(
    *,
    vault_root: Path | str,
    queries: tuple[str, ...],
    clients: Mapping[str, InspirationSearchClient] | None = None,
    config: InspirationRefreshConfig = InspirationRefreshConfig(),
    write_summary: bool = True,
) -> InspirationRefreshReport:
    """Search non-scholarly sources and write an Obsidian-safe summary."""

    selected_queries = _select_queries(queries=queries, config=config)
    source_clients: Mapping[str, InspirationSearchClient]
    if clients is None:
        source_clients = {
            "huggingface_datasets": HuggingFaceDatasetClient(),
            "hacker_news": HackerNewsSearchClient(),
        }
    else:
        source_clients = clients
    fetches: list[InspirationFetchRecord] = []
    items: list[InspirationItem] = []
    for query in selected_queries:
        for source_name, client in source_clients.items():
            source_items: list[InspirationItem] = []
            error: str | None = None
            try:
                source_items = client.search(query, limit=config.max_results_per_source)
            except Exception as exc:  # noqa: BLE001 - source failures must be visible.
                error = f"{type(exc).__name__}: {exc}"
            items.extend(source_items)
            fetches.append(
                InspirationFetchRecord(
                    source=source_name,
                    source_type=client.source_type,
                    query=query,
                    result_count=len(source_items),
                    rate_limit_seconds=client.rate_limit_seconds,
                    error=error,
                )
            )
    deduplicated_items = _deduplicate_items(items)
    report = InspirationRefreshReport(
        queries=tuple(selected_queries),
        fetches=tuple(fetches),
        items=deduplicated_items,
        summary_path=None,
    )
    if write_summary:
        summary_path = _write_inspiration_summary(Path(vault_root), report)
        report = InspirationRefreshReport(
            queries=report.queries,
            fetches=report.fetches,
            items=report.items,
            summary_path=summary_path,
        )
    return report


def _urllib_get_json(
    url: str,
    params: dict[str, str | int],
    headers: Mapping[str, str] | None = None,
) -> object:
    query = urllib.parse.urlencode(params)
    request_headers = {"User-Agent": "ai-researcher/0.1"}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(f"{url}?{query}", headers=request_headers)
    context = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(request, timeout=30, context=context) as response:
        return json.loads(cast(bytes, response.read()).decode("utf-8"))


def _select_queries(
    *,
    queries: tuple[str, ...],
    config: InspirationRefreshConfig,
) -> tuple[str, ...]:
    if config.max_queries < 1:
        msg = "max_queries must be at least 1"
        raise ValueError(msg)
    if config.max_results_per_source < 1:
        msg = "max_results_per_source must be at least 1"
        raise ValueError(msg)
    candidates = [_clean_query(query) for query in [*queries, *config.seed_queries]]
    cleaned = _ordered_unique(query for query in candidates if query)
    if not cleaned:
        cleaned = (
            "autonomous research agents datasets",
            "AI research workflow tools",
            "scientific agent benchmark data",
        )
    return tuple(cleaned[: config.max_queries])


def _write_inspiration_summary(root: Path, report: InspirationRefreshReport) -> Path:
    timestamp = datetime.now(timezone.utc)
    date_id = timestamp.strftime("%Y%m%d")
    entry = KnowledgeEntry(
        entry_id=f"inspiration_refresh_{date_id}",
        entry_type=KnowledgeEntryType.EVIDENCE_NOTE,
        zone=KnowledgeZone.EXPLORATION,
        title=f"Broad inspiration refresh {date_id}",
        tags=["inspiration", "non-scholarly", "dataset-signal", "forum-signal"],
        keywords=list(report.queries),
        source_refs=[item.url for item in report.items],
        body=_inspiration_summary_body(report),
    )
    relative_path = Path("exploration") / "inspiration" / f"inspiration_refresh_{date_id}.md"
    return MarkdownKnowledgeStore(root).write_entry(relative_path, entry)


def _inspiration_summary_body(report: InspirationRefreshReport) -> str:
    lines = [
        "# Broad inspiration refresh",
        "",
        "This note records dataset/community/news inspiration signals only.",
        "Do not cite these items as scholarly evidence without separate source validation.",
        "",
        "## Queries",
        "",
        *[f"- `{query}`" for query in report.queries],
        "",
        "## Fetches",
        "",
    ]
    for fetch in report.fetches:
        error = f"; error: `{fetch.error}`" if fetch.error else ""
        lines.append(
            f"- `{fetch.source}` ({fetch.source_type}) query `{fetch.query}` -> "
            f"`{fetch.result_count}` items, rate limit `{fetch.rate_limit_seconds}` seconds{error}."
        )
    lines.extend(["", "## Items", ""])
    for item in sorted(report.items, key=lambda row: (-row.score, row.source, row.title.casefold())):
        lines.append(
            f"- [{item.title}]({item.url}) - `{item.source}` `{item.source_type}`, "
            f"score `{item.score:.1f}`, query `{item.query}`."
        )
        lines.append(f"  - {item.summary}")
    return "\n".join(lines).rstrip() + "\n"


def _deduplicate_items(items: list[InspirationItem]) -> tuple[InspirationItem, ...]:
    by_key: dict[tuple[str, str], InspirationItem] = {}
    for item in items:
        key = (item.source, item.url.casefold())
        existing = by_key.get(key)
        if existing is None or item.score > existing.score:
            by_key[key] = item
    return tuple(sorted(by_key.values(), key=lambda row: (row.source, -row.score, row.title)))


def _clean_query(query: str) -> str:
    return " ".join(query.split()).strip()


def _ordered_unique(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for raw_value in values:
        value = str(raw_value).strip()
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            result.append(value)
    return tuple(result)


def _string(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _number(value: object) -> float:
    if isinstance(value, int | float):
        return float(value)
    return 0.0
