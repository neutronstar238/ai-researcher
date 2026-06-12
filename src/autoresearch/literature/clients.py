"""Literature API clients with retry and rate limiting."""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any, cast

from .models import AcademicPaper

HttpGet = Callable[[str, dict[str, str | int]], str]


@dataclass(frozen=True)
class RetryConfig:
    max_attempts: int = 3
    backoff_seconds: float = 0.5


class RateLimiter:
    """Small injectable rate limiter for API clients."""

    def __init__(
        self,
        min_interval_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.min_interval_seconds = min_interval_seconds
        self.clock = clock
        self.sleep = sleep
        self._last_call: float | None = None

    def wait(self) -> None:
        now = self.clock()
        if self._last_call is not None:
            remaining = self.min_interval_seconds - (now - self._last_call)
            if remaining > 0:
                self.sleep(remaining)
                now = self.clock()
        self._last_call = now


def _urllib_get_text(url: str, params: dict[str, str | int]) -> str:
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{url}?{query}",
        headers={"User-Agent": "ai-researcher/0.1"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return cast(bytes, response.read()).decode("utf-8")


class ArxivClient:
    """Minimal ArXiv Atom API client."""

    api_url = "https://export.arxiv.org/api/query"

    def __init__(
        self,
        *,
        http_get: HttpGet = _urllib_get_text,
        rate_limiter: RateLimiter | None = None,
        retry: RetryConfig = RetryConfig(),
    ) -> None:
        self.http_get = http_get
        self.rate_limiter = rate_limiter or RateLimiter(3.0)
        self.retry = retry

    def search(self, query: str, *, limit: int = 10) -> list[AcademicPaper]:
        params: dict[str, str | int] = {
            "search_query": query,
            "start": 0,
            "max_results": limit,
        }
        text = self._get_with_retry(self.api_url, params)
        return _parse_arxiv_atom(text)

    def _get_with_retry(self, url: str, params: dict[str, str | int]) -> str:
        last_error: Exception | None = None
        for attempt in range(1, self.retry.max_attempts + 1):
            self.rate_limiter.wait()
            try:
                return self.http_get(url, params)
            except Exception as exc:  # noqa: BLE001 - client boundary wraps transport errors.
                last_error = exc
                if attempt < self.retry.max_attempts:
                    time.sleep(self.retry.backoff_seconds * attempt)
        if last_error is not None:
            raise last_error
        raise RuntimeError("retry loop exited without request")


class SemanticScholarClient:
    """Minimal Semantic Scholar Graph API client."""

    api_url = "https://api.semanticscholar.org/graph/v1/paper/search"

    def __init__(
        self,
        *,
        http_get: HttpGet = _urllib_get_text,
        rate_limiter: RateLimiter | None = None,
        retry: RetryConfig = RetryConfig(),
    ) -> None:
        self.http_get = http_get
        self.rate_limiter = rate_limiter or RateLimiter(1.0)
        self.retry = retry

    def search(self, query: str, *, limit: int = 10) -> list[AcademicPaper]:
        params: dict[str, str | int] = {
            "query": query,
            "limit": limit,
            "fields": "title,authors,abstract,year,venue,url,citationCount,externalIds",
        }
        text = self._get_with_retry(self.api_url, params)
        return _parse_semantic_scholar(text)

    def _get_with_retry(self, url: str, params: dict[str, str | int]) -> str:
        last_error: Exception | None = None
        for attempt in range(1, self.retry.max_attempts + 1):
            self.rate_limiter.wait()
            try:
                return self.http_get(url, params)
            except Exception as exc:  # noqa: BLE001 - client boundary wraps transport errors.
                last_error = exc
                if attempt < self.retry.max_attempts:
                    time.sleep(self.retry.backoff_seconds * attempt)
        if last_error is not None:
            raise last_error
        raise RuntimeError("retry loop exited without request")


def _parse_arxiv_atom(text: str) -> list[AcademicPaper]:
    root = ET.fromstring(text)
    namespace = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    papers: list[AcademicPaper] = []
    for entry in root.findall("atom:entry", namespace):
        title = _xml_text(entry, "atom:title", namespace)
        if title is None:
            continue
        published = _xml_text(entry, "atom:published", namespace)
        doi = _xml_text(entry, "arxiv:doi", namespace)
        url = _xml_text(entry, "atom:id", namespace)
        authors = [
            author_name
            for author in entry.findall("atom:author", namespace)
            if (author_name := _xml_text(author, "atom:name", namespace)) is not None
        ]
        papers.append(
            AcademicPaper(
                title=" ".join(title.split()),
                authors=authors,
                abstract=_clean_optional_text(_xml_text(entry, "atom:summary", namespace)),
                publication_date=_parse_date(published),
                doi=doi,
                url=url,
                citation_count=0,
                source="arxiv",
            )
        )
    return papers


def _parse_semantic_scholar(text: str) -> list[AcademicPaper]:
    payload = json.loads(text)
    rows = payload.get("data", [])
    papers: list[AcademicPaper] = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("title"), str):
            continue
        external_ids = row.get("externalIds", {})
        doi = external_ids.get("DOI") if isinstance(external_ids, dict) else None
        authors = row.get("authors", [])
        papers.append(
            AcademicPaper(
                title=row["title"],
                authors=[author["name"] for author in authors if isinstance(author, dict) and "name" in author],
                abstract=row.get("abstract") if isinstance(row.get("abstract"), str) else None,
                publication_date=_parse_year(row.get("year")),
                venue=row.get("venue") if isinstance(row.get("venue"), str) else None,
                doi=doi if isinstance(doi, str) else None,
                url=row.get("url") if isinstance(row.get("url"), str) else None,
                citation_count=row.get("citationCount", 0)
                if isinstance(row.get("citationCount"), int)
                else 0,
                source="semantic_scholar",
            )
        )
    return papers


def _xml_text(element: ET.Element, path: str, namespace: dict[str, str]) -> str | None:
    child = element.find(path, namespace)
    return child.text.strip() if child is not None and child.text is not None else None


def _clean_optional_text(value: str | None) -> str | None:
    return " ".join(value.split()) if value is not None else None


def _parse_date(value: str | None) -> date | None:
    if value is None:
        return None
    return date.fromisoformat(value[:10])


def _parse_year(value: Any) -> date | None:
    return date(int(value), 1, 1) if isinstance(value, int) else None
