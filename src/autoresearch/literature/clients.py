"""Literature API clients with retry and rate limiting."""

from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, cast

import certifi

from .models import AcademicPaper

HttpGet = Callable[[str, dict[str, str | int], Mapping[str, str] | None], str]


@dataclass(frozen=True)
class RetryConfig:
    max_attempts: int = 3
    backoff_seconds: float = 0.5
    max_backoff_seconds: float = 8.0


class SourceRateLimitError(RuntimeError):
    """Raised when a source explicitly rate-limits the client."""


class CircuitBreakerOpenError(RuntimeError):
    """Raised when a source circuit breaker is open after rate limiting."""


class RateLimitCircuitBreaker:
    """Short-circuit repeated requests after explicit source rate limits."""

    def __init__(
        self,
        *,
        failure_threshold: int = 1,
        reset_after_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if failure_threshold < 1:
            msg = "failure_threshold must be at least 1"
            raise ValueError(msg)
        if reset_after_seconds < 0:
            msg = "reset_after_seconds must be non-negative"
            raise ValueError(msg)
        self.failure_threshold = failure_threshold
        self.reset_after_seconds = reset_after_seconds
        self.clock = clock
        self._failures = 0
        self._opened_until: float | None = None

    def raise_if_open(self) -> None:
        remaining = self.remaining_seconds()
        if remaining > 0:
            msg = f"rate-limit circuit is open for {remaining:.1f}s"
            raise CircuitBreakerOpenError(msg)
        if self._opened_until is not None:
            self.record_success()

    def record_rate_limit(self, *, retry_after_seconds: float | None = None) -> None:
        self._failures += 1
        if self._failures < self.failure_threshold:
            return
        cooldown = max(self.reset_after_seconds, retry_after_seconds or 0.0)
        self._opened_until = self.clock() + cooldown

    def record_success(self) -> None:
        self._failures = 0
        self._opened_until = None

    def remaining_seconds(self) -> float:
        if self._opened_until is None:
            return 0.0
        return max(0.0, self._opened_until - self.clock())


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


def _urllib_get_text(
    url: str,
    params: dict[str, str | int],
    headers: Mapping[str, str] | None = None,
) -> str:
    query = urllib.parse.urlencode(params)
    request_headers = {"User-Agent": "ai-researcher/0.1"}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(
        f"{url}?{query}",
        headers=request_headers,
    )
    context = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(request, timeout=30, context=context) as response:
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
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.http_get = http_get
        self.rate_limiter = rate_limiter or RateLimiter(3.0)
        self.retry = retry
        self.sleep = sleep

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
                return self.http_get(url, params, None)
            except Exception as exc:  # noqa: BLE001 - client boundary wraps transport errors.
                last_error = exc
                if attempt < self.retry.max_attempts:
                    self.sleep(_backoff_delay(self.retry, attempt))
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
        api_key: str | None = None,
        api_key_env: str = "SEMANTIC_SCHOLAR_API_KEY",
        circuit_breaker: RateLimitCircuitBreaker | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.http_get = http_get
        self.api_key = api_key if api_key is not None else os.getenv(api_key_env)
        self.rate_limiter = rate_limiter or RateLimiter(1.0 if self.api_key else 3.0)
        self.retry = retry
        self.circuit_breaker = circuit_breaker or RateLimitCircuitBreaker()
        self.sleep = sleep

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
            self.circuit_breaker.raise_if_open()
            self.rate_limiter.wait()
            try:
                text = self.http_get(url, params, self._request_headers())
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code == 429:
                    retry_after = _retry_after_seconds(exc)
                    self.circuit_breaker.record_rate_limit(
                        retry_after_seconds=retry_after,
                    )
                    remaining = self.circuit_breaker.remaining_seconds()
                    msg = f"Semantic Scholar HTTP 429 rate limited; circuit open for {remaining:.1f}s"
                    raise SourceRateLimitError(msg) from exc
                if _non_retryable_http_error(exc):
                    raise
                if attempt < self.retry.max_attempts:
                    self.sleep(_backoff_delay(self.retry, attempt))
            except Exception as exc:  # noqa: BLE001 - client boundary wraps transport errors.
                last_error = exc
                if attempt < self.retry.max_attempts:
                    self.sleep(_backoff_delay(self.retry, attempt))
            else:
                self.circuit_breaker.record_success()
                return text
        if last_error is not None:
            raise last_error
        raise RuntimeError("retry loop exited without request")

    def _request_headers(self) -> Mapping[str, str] | None:
        if not self.api_key:
            return None
        return {"x-api-key": self.api_key}


def _backoff_delay(retry: RetryConfig, attempt: int) -> float:
    return float(min(retry.backoff_seconds * (2 ** (attempt - 1)), retry.max_backoff_seconds))


def _non_retryable_http_error(exc: urllib.error.HTTPError) -> bool:
    return 400 <= exc.code < 500 and exc.code != 429


def _retry_after_seconds(exc: urllib.error.HTTPError) -> float | None:
    retry_after = exc.headers.get("Retry-After") if exc.headers is not None else None
    if retry_after is None:
        return None
    try:
        return max(0.0, float(retry_after))
    except ValueError:
        return None


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
