"""Literature API clients with retry and rate limiting."""

from __future__ import annotations

import json
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Literal, cast

import certifi

from .models import AcademicPaper, PublicationStatus, normalize_doi

HttpGet = Callable[[str, dict[str, str | int], Mapping[str, str] | None], str]
OPTIONAL_LITERATURE_SOURCES = frozenset({"semantic_scholar"})
OPENALEX_TITLE_ABSTRACT_FILTER_PREFIX = "title_and_abstract.search:"
OPENALEX_SELECT_FIELDS = (
    "id,display_name,doi,publication_date,publication_year,authorships,"
    "abstract_inverted_index,primary_location,cited_by_count,type,is_retracted"
)
SEMANTIC_SCHOLAR_SEARCH_FIELDS = "title,authors,abstract,year,venue,url,citationCount,externalIds"


@dataclass(frozen=True)
class SourceHTTPAttemptEvent:
    """One physical public-source HTTP attempt boundary event.

    Only credential-free request metadata is exposed. Response text and the
    exception object are transient inputs for a caller-owned recorder and are
    deliberately excluded from ``repr``.
    """

    phase: Literal["reservation", "completed", "failed"]
    source: str
    operation: Literal["literature_search", "paper_status_verification"]
    endpoint: str
    public_params: Mapping[str, str | int]
    excluded_credential_fields: tuple[str, ...]
    attempt_index: int
    max_attempts: int
    response_text: str | None = field(default=None, repr=False)
    error: BaseException | None = field(default=None, repr=False)


SourceHTTPAttemptObserver = Callable[[SourceHTTPAttemptEvent], None]
_SOURCE_HTTP_ATTEMPT_OBSERVER: ContextVar[SourceHTTPAttemptObserver | None] = ContextVar(
    "autoresearch_source_http_attempt_observer",
    default=None,
)
_PRIVATE_SOURCE_PARAMETER_FIELDS = frozenset({"api_key", "mailto"})


@contextmanager
def bind_source_http_attempt_observer(
    observer: SourceHTTPAttemptObserver,
) -> Iterator[None]:
    """Bind a synchronous recorder around one logical source operation."""

    parent = _SOURCE_HTTP_ATTEMPT_OBSERVER.get()

    def notify(event: SourceHTTPAttemptEvent) -> None:
        if parent is not None:
            parent(event)
        observer(event)

    token = _SOURCE_HTTP_ATTEMPT_OBSERVER.set(notify)
    try:
        yield
    finally:
        _SOURCE_HTTP_ATTEMPT_OBSERVER.reset(token)


def source_http_attempt_tracing_supported(call: Callable[..., Any]) -> bool:
    """Return whether a bound source callable emits physical attempt events."""

    owner = getattr(call, "__self__", None)
    function = getattr(call, "__func__", None)
    return bool(
        (type(owner) is ArxivClient and function in (ArxivClient.search, ArxivClient.verify_status))
        or (type(owner) is OpenAlexClient and function is OpenAlexClient.search)
        or (type(owner) is SemanticScholarClient and function is SemanticScholarClient.search)
    )


def _emit_source_http_attempt(
    *,
    phase: Literal["reservation", "completed", "failed"],
    source: str,
    operation: Literal["literature_search", "paper_status_verification"],
    endpoint: str,
    params: Mapping[str, str | int],
    attempt_index: int,
    max_attempts: int,
    excluded_credential_fields: tuple[str, ...] = (),
    response_text: str | None = None,
    error: BaseException | None = None,
) -> None:
    observer = _SOURCE_HTTP_ATTEMPT_OBSERVER.get()
    if observer is None:
        return
    private_fields = tuple(
        sorted(
            {
                *excluded_credential_fields,
                *(field for field in params if field in _PRIVATE_SOURCE_PARAMETER_FIELDS),
            }
        )
    )
    public_params = {
        str(key): value
        for key, value in params.items()
        if key not in _PRIVATE_SOURCE_PARAMETER_FIELDS
    }
    observer(
        SourceHTTPAttemptEvent(
            phase=phase,
            source=source,
            operation=operation,
            endpoint=endpoint,
            public_params=public_params,
            excluded_credential_fields=private_fields,
            attempt_index=attempt_index,
            max_attempts=max_attempts,
            response_text=response_text,
            error=error,
        )
    )


@dataclass(frozen=True)
class RetryConfig:
    max_attempts: int = 3
    backoff_seconds: float = 0.5
    max_backoff_seconds: float = 8.0


def semantic_scholar_enabled() -> bool:
    """Return whether the optional Semantic Scholar source should be queried."""

    explicit = os.getenv("AUTORESEARCH_ENABLE_SEMANTIC_SCHOLAR")
    if explicit is not None and explicit.strip():
        return explicit.strip().lower() in {"1", "true", "yes", "on"}
    return bool((os.getenv("SEMANTIC_SCHOLAR_API_KEY") or "").strip())


class SourceRateLimitError(RuntimeError):
    """Raised when a source explicitly rate-limits the client."""


class CircuitBreakerOpenError(RuntimeError):
    """Raised when a source circuit breaker is open after rate limiting."""


class SourceCircuitStateLockError(RuntimeError):
    """Raised when persisted source circuit state cannot be locked."""


class RateLimitCircuitBreaker:
    """Short-circuit repeated requests after explicit source rate limits."""

    def __init__(
        self,
        *,
        failure_threshold: int = 1,
        reset_after_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        state_path: Path | str | None = None,
        state_key: str = "default",
        state_lock_timeout_seconds: float = 5.0,
        state_stale_lock_seconds: float = 300.0,
    ) -> None:
        if failure_threshold < 1:
            msg = "failure_threshold must be at least 1"
            raise ValueError(msg)
        if reset_after_seconds < 0:
            msg = "reset_after_seconds must be non-negative"
            raise ValueError(msg)
        if state_lock_timeout_seconds < 0:
            msg = "state_lock_timeout_seconds must be non-negative"
            raise ValueError(msg)
        if state_stale_lock_seconds < 0:
            msg = "state_stale_lock_seconds must be non-negative"
            raise ValueError(msg)
        self.failure_threshold = failure_threshold
        self.reset_after_seconds = reset_after_seconds
        self.clock = clock
        self.wall_clock = wall_clock
        self.state_path = Path(state_path) if state_path is not None else None
        self.state_key = state_key
        self.state_lock_timeout_seconds = state_lock_timeout_seconds
        self.state_stale_lock_seconds = state_stale_lock_seconds
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
        self._set_persistent_open(cooldown)

    def record_success(self) -> None:
        self._failures = 0
        self._opened_until = None
        self._clear_persistent_open()

    def remaining_seconds(self) -> float:
        persistent_remaining = self._persistent_remaining_seconds()
        if self._opened_until is None:
            return persistent_remaining
        return max(persistent_remaining, max(0.0, self._opened_until - self.clock()))

    def _persistent_remaining_seconds(self) -> float:
        if self.state_path is None:
            return 0.0
        state = self._read_state()
        value = state.get(self.state_key)
        if not isinstance(value, int | float):
            return 0.0
        remaining = float(value) - self.wall_clock()
        if remaining <= 0:
            self._clear_persistent_open()
            return 0.0
        return remaining

    def _set_persistent_open(self, cooldown_seconds: float) -> None:
        if self.state_path is None:
            return
        with self._state_file_lock():
            state = self._read_state()
            state[self.state_key] = self.wall_clock() + cooldown_seconds
            self._write_state(state)

    def _clear_persistent_open(self) -> None:
        if self.state_path is None:
            return
        with self._state_file_lock():
            state = self._read_state()
            if self.state_key not in state:
                return
            state.pop(self.state_key, None)
            self._write_state(state)

    def _read_state(self) -> dict[str, float]:
        if self.state_path is None or not self.state_path.exists():
            return {}
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {
            str(key): float(value)
            for key, value in payload.items()
            if isinstance(value, int | float)
        }

    def _write_state(self, state: Mapping[str, float]) -> None:
        if self.state_path is None:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(dict(sorted(state.items())), indent=2, sort_keys=True)
        temp_path = self.state_path.with_name(
            f".{self.state_path.name}.{os.getpid()}.{time.time_ns()}.tmp"
        )
        try:
            temp_path.write_text(payload, encoding="utf-8")
            temp_path.replace(self.state_path)
        finally:
            with suppress(FileNotFoundError):
                temp_path.unlink()

    @contextmanager
    def _state_file_lock(self) -> Iterator[None]:
        if self.state_path is None:
            yield
            return
        lock_path = self.state_path.with_name(f"{self.state_path.name}.lock")
        deadline = time.monotonic() + self.state_lock_timeout_seconds
        acquired = False
        while not acquired:
            try:
                lock_path.parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try:
                    payload = json.dumps(
                        {"created_at": self.wall_clock(), "pid": os.getpid()},
                        sort_keys=True,
                    )
                    os.write(fd, payload.encode("utf-8"))
                finally:
                    os.close(fd)
                acquired = True
            except FileExistsError as exc:
                if self._state_lock_is_stale(lock_path):
                    with suppress(FileNotFoundError):
                        lock_path.unlink()
                    continue
                if time.monotonic() >= deadline:
                    msg = f"source circuit state is locked: {lock_path}"
                    raise SourceCircuitStateLockError(msg) from exc
                time.sleep(min(0.05, max(deadline - time.monotonic(), 0.0)))

        try:
            yield
        finally:
            with suppress(FileNotFoundError):
                lock_path.unlink()

    def _state_lock_is_stale(self, lock_path: Path) -> bool:
        if self.state_stale_lock_seconds <= 0:
            return False
        try:
            age_seconds = self.wall_clock() - lock_path.stat().st_mtime
        except FileNotFoundError:
            return False
        return age_seconds > self.state_stale_lock_seconds


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
        text = self._get_with_retry(
            self.api_url,
            params,
            operation="literature_search",
        )
        return _parse_arxiv_atom(text)

    def verify_status(self, paper: AcademicPaper) -> AcademicPaper:
        """Verify one shortlisted arXiv record against its abstract page.

        Status verification is deliberately separate from search so a caller can
        enrich only shortlisted records. The request shares the normal arXiv rate
        limiter and retry policy instead of multiplying requests for every hit.
        """

        if paper.source != "arxiv" or paper.url is None:
            return paper
        status = _parse_arxiv_abs_status(
            self._get_with_retry(
                paper.url,
                {},
                operation="paper_status_verification",
            )
        )
        if status is None:
            return paper
        return paper.model_copy(
            update={
                "publication_status": status,
                "status_source": "arxiv_abs",
                "status_as_of": date.today(),
            }
        )

    def _get_with_retry(
        self,
        url: str,
        params: dict[str, str | int],
        *,
        operation: Literal["literature_search", "paper_status_verification"],
    ) -> str:
        last_error: Exception | None = None
        for attempt in range(1, self.retry.max_attempts + 1):
            self.rate_limiter.wait()
            _emit_source_http_attempt(
                phase="reservation",
                source="arxiv",
                operation=operation,
                endpoint=url,
                params=params,
                attempt_index=attempt,
                max_attempts=self.retry.max_attempts,
            )
            try:
                text = self.http_get(url, params, None)
            except Exception as exc:  # noqa: BLE001 - client boundary wraps transport errors.
                last_error = exc
                _emit_source_http_attempt(
                    phase="failed",
                    source="arxiv",
                    operation=operation,
                    endpoint=url,
                    params=params,
                    attempt_index=attempt,
                    max_attempts=self.retry.max_attempts,
                    error=exc,
                )
                if attempt < self.retry.max_attempts:
                    self.sleep(_backoff_delay(self.retry, attempt))
            else:
                _emit_source_http_attempt(
                    phase="completed",
                    source="arxiv",
                    operation=operation,
                    endpoint=url,
                    params=params,
                    attempt_index=attempt,
                    max_attempts=self.retry.max_attempts,
                    response_text=text,
                )
                return text
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
        circuit_state_path: Path | str | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.http_get = http_get
        self.api_key = api_key if api_key is not None else os.getenv(api_key_env)
        default_interval = 1.0 if self.api_key else 3.0
        self.rate_limiter = rate_limiter or RateLimiter(
            _float_env("SEMANTIC_SCHOLAR_MIN_INTERVAL_SECONDS", default_interval)
        )
        self.retry = retry
        self.circuit_breaker = circuit_breaker or RateLimitCircuitBreaker(
            reset_after_seconds=_float_env("SEMANTIC_SCHOLAR_CIRCUIT_RESET_SECONDS", 60.0),
            state_path=circuit_state_path,
            state_key="semantic_scholar",
        )
        self.sleep = sleep

    def search(self, query: str, *, limit: int = 10) -> list[AcademicPaper]:
        params: dict[str, str | int] = {
            "query": query,
            "limit": limit,
            "fields": SEMANTIC_SCHOLAR_SEARCH_FIELDS,
        }
        text = self._get_with_retry(self.api_url, params)
        return _parse_semantic_scholar(text)

    def _get_with_retry(self, url: str, params: dict[str, str | int]) -> str:
        last_error: Exception | None = None
        for attempt in range(1, self.retry.max_attempts + 1):
            self.circuit_breaker.raise_if_open()
            self.rate_limiter.wait()
            excluded_credentials = ("headers.x-api-key",) if self.api_key else ()
            _emit_source_http_attempt(
                phase="reservation",
                source="semantic_scholar",
                operation="literature_search",
                endpoint=url,
                params=params,
                attempt_index=attempt,
                max_attempts=self.retry.max_attempts,
                excluded_credential_fields=excluded_credentials,
            )
            try:
                text = self.http_get(url, params, self._request_headers())
            except urllib.error.HTTPError as exc:
                last_error = exc
                _emit_source_http_attempt(
                    phase="failed",
                    source="semantic_scholar",
                    operation="literature_search",
                    endpoint=url,
                    params=params,
                    attempt_index=attempt,
                    max_attempts=self.retry.max_attempts,
                    excluded_credential_fields=excluded_credentials,
                    error=exc,
                )
                if exc.code == 429:
                    retry_after = _retry_after_seconds(exc)
                    self.circuit_breaker.record_rate_limit(
                        retry_after_seconds=retry_after,
                    )
                    remaining = self.circuit_breaker.remaining_seconds()
                    msg = (
                        f"Semantic Scholar HTTP 429 rate limited; circuit open for {remaining:.1f}s"
                    )
                    raise SourceRateLimitError(msg) from exc
                if _non_retryable_http_error(exc):
                    raise
                if attempt < self.retry.max_attempts:
                    self.sleep(_backoff_delay(self.retry, attempt))
            except Exception as exc:  # noqa: BLE001 - client boundary wraps transport errors.
                last_error = exc
                _emit_source_http_attempt(
                    phase="failed",
                    source="semantic_scholar",
                    operation="literature_search",
                    endpoint=url,
                    params=params,
                    attempt_index=attempt,
                    max_attempts=self.retry.max_attempts,
                    excluded_credential_fields=excluded_credentials,
                    error=exc,
                )
                if attempt < self.retry.max_attempts:
                    self.sleep(_backoff_delay(self.retry, attempt))
            else:
                self.circuit_breaker.record_success()
                _emit_source_http_attempt(
                    phase="completed",
                    source="semantic_scholar",
                    operation="literature_search",
                    endpoint=url,
                    params=params,
                    attempt_index=attempt,
                    max_attempts=self.retry.max_attempts,
                    excluded_credential_fields=excluded_credentials,
                    response_text=text,
                )
                return text
        if last_error is not None:
            raise last_error
        raise RuntimeError("retry loop exited without request")

    def _request_headers(self) -> Mapping[str, str] | None:
        if not self.api_key:
            return None
        return {"x-api-key": self.api_key}


class OpenAlexClient:
    """Minimal OpenAlex Works API client."""

    api_url = "https://api.openalex.org/works"

    def __init__(
        self,
        *,
        http_get: HttpGet = _urllib_get_text,
        rate_limiter: RateLimiter | None = None,
        retry: RetryConfig = RetryConfig(),
        api_key: str | None = None,
        api_key_env: str = "OPENALEX_API_KEY",
        mailto: str | None = None,
        mailto_env: str = "OPENALEX_MAILTO",
        circuit_breaker: RateLimitCircuitBreaker | None = None,
        circuit_state_path: Path | str | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.http_get = http_get
        self.api_key = api_key if api_key is not None else os.getenv(api_key_env)
        self.mailto = mailto if mailto is not None else os.getenv(mailto_env)
        self.rate_limiter = rate_limiter or RateLimiter(
            _float_env("OPENALEX_MIN_INTERVAL_SECONDS", 1.0)
        )
        self.retry = retry
        self.circuit_breaker = circuit_breaker or RateLimitCircuitBreaker(
            reset_after_seconds=_float_env("OPENALEX_CIRCUIT_RESET_SECONDS", 60.0),
            state_path=circuit_state_path,
            state_key="openalex",
        )
        self.sleep = sleep

    def search(self, query: str, *, limit: int = 10) -> list[AcademicPaper]:
        params: dict[str, str | int] = {
            "per_page": min(max(limit, 1), 100),
            "select": OPENALEX_SELECT_FIELDS,
        }
        if query.startswith(OPENALEX_TITLE_ABSTRACT_FILTER_PREFIX):
            if not query.removeprefix(OPENALEX_TITLE_ABSTRACT_FILTER_PREFIX).strip():
                raise ValueError("OpenAlex title-and-abstract filter must not be blank")
            params["filter"] = query
        else:
            # Preserve the historical v1 adapter exactly for replayable old requests.
            params["search"] = query[:1200]
        if self.api_key:
            params["api_key"] = self.api_key
        if self.mailto:
            params["mailto"] = self.mailto
        text = self._get_with_retry(self.api_url, params)
        return _parse_openalex(text)

    def _get_with_retry(self, url: str, params: dict[str, str | int]) -> str:
        last_error: Exception | None = None
        for attempt in range(1, self.retry.max_attempts + 1):
            self.circuit_breaker.raise_if_open()
            self.rate_limiter.wait()
            _emit_source_http_attempt(
                phase="reservation",
                source="openalex",
                operation="literature_search",
                endpoint=url,
                params=params,
                attempt_index=attempt,
                max_attempts=self.retry.max_attempts,
            )
            try:
                text = self.http_get(url, params, None)
            except urllib.error.HTTPError as exc:
                last_error = exc
                _emit_source_http_attempt(
                    phase="failed",
                    source="openalex",
                    operation="literature_search",
                    endpoint=url,
                    params=params,
                    attempt_index=attempt,
                    max_attempts=self.retry.max_attempts,
                    error=exc,
                )
                if exc.code == 429:
                    retry_after = _retry_after_seconds(exc)
                    self.circuit_breaker.record_rate_limit(retry_after_seconds=retry_after)
                    remaining = self.circuit_breaker.remaining_seconds()
                    msg = f"OpenAlex HTTP 429 rate limited; circuit open for {remaining:.1f}s"
                    raise SourceRateLimitError(msg) from exc
                if _non_retryable_http_error(exc):
                    raise
                if attempt < self.retry.max_attempts:
                    self.sleep(_backoff_delay(self.retry, attempt))
            except Exception as exc:  # noqa: BLE001 - client boundary wraps transport errors.
                last_error = exc
                _emit_source_http_attempt(
                    phase="failed",
                    source="openalex",
                    operation="literature_search",
                    endpoint=url,
                    params=params,
                    attempt_index=attempt,
                    max_attempts=self.retry.max_attempts,
                    error=exc,
                )
                if attempt < self.retry.max_attempts:
                    self.sleep(_backoff_delay(self.retry, attempt))
            else:
                self.circuit_breaker.record_success()
                _emit_source_http_attempt(
                    phase="completed",
                    source="openalex",
                    operation="literature_search",
                    endpoint=url,
                    params=params,
                    attempt_index=attempt,
                    max_attempts=self.retry.max_attempts,
                    response_text=text,
                )
                return text
        if last_error is not None:
            raise last_error
        raise RuntimeError("retry loop exited without request")


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


def _float_env(name: str, default: float, *, minimum: float = 0.0) -> float:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value.strip() == "":
        return default
    try:
        value = float(raw_value)
    except ValueError as exc:
        msg = f"{name} must be a number"
        raise ValueError(msg) from exc
    if value < minimum:
        msg = f"{name} must be at least {minimum}"
        raise ValueError(msg)
    return value


def _parse_arxiv_atom(text: str) -> list[AcademicPaper]:
    root = ET.fromstring(text)
    namespace = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    papers: list[AcademicPaper] = []
    for entry in root.findall("atom:entry", namespace):
        title = _xml_text(entry, "atom:title", namespace)
        if title is None:
            continue
        published = _xml_text(entry, "atom:published", namespace)
        raw_doi = _xml_text(entry, "arxiv:doi", namespace)
        url = _xml_text(entry, "atom:id", namespace)
        comment = _xml_text(entry, "arxiv:comment", namespace)
        doi, source_repository_doi = _classify_doi(raw_doi)
        repository_doi = source_repository_doi or _arxiv_repository_doi(url)
        publication_status = _arxiv_atom_status(title=title, comment=comment)
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
                repository_doi=repository_doi,
                url=url,
                citation_count=None,
                publication_status=publication_status,
                status_source="arxiv_atom",
                status_as_of=date.today(),
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
        raw_doi = external_ids.get("DOI") if isinstance(external_ids, dict) else None
        doi, repository_doi = _classify_doi(raw_doi)
        authors = row.get("authors", [])
        citation_count = _parse_citation_count(row.get("citationCount"))
        papers.append(
            AcademicPaper(
                title=row["title"],
                authors=[
                    author["name"]
                    for author in authors
                    if isinstance(author, dict) and "name" in author
                ],
                abstract=row.get("abstract") if isinstance(row.get("abstract"), str) else None,
                publication_date=_parse_year(row.get("year")),
                venue=row.get("venue") if isinstance(row.get("venue"), str) else None,
                doi=doi,
                repository_doi=repository_doi,
                url=row.get("url") if isinstance(row.get("url"), str) else None,
                citation_count=citation_count,
                citation_count_source="semantic_scholar" if citation_count is not None else None,
                citation_count_as_of=date.today() if citation_count is not None else None,
                source="semantic_scholar",
            )
        )
    return papers


def _parse_openalex(text: str) -> list[AcademicPaper]:
    payload = json.loads(text)
    rows = payload.get("results", [])
    papers: list[AcademicPaper] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw_title = row.get("display_name")
        if not isinstance(raw_title, str) or not (title := raw_title.strip()):
            continue
        primary_location = row.get("primary_location")
        source = primary_location.get("source") if isinstance(primary_location, dict) else None
        venue = source.get("display_name") if isinstance(source, dict) else None
        landing_page = (
            primary_location.get("landing_page_url") if isinstance(primary_location, dict) else None
        )
        doi, repository_doi = _classify_doi(row.get("doi"))
        citation_count = _parse_citation_count(row.get("cited_by_count"))
        publication_status = _openalex_publication_status(row)
        papers.append(
            AcademicPaper(
                title=title,
                authors=_openalex_authors(row.get("authorships")),
                abstract=_openalex_abstract(row.get("abstract_inverted_index")),
                publication_date=_parse_date(row.get("publication_date"))
                if isinstance(row.get("publication_date"), str)
                else _parse_year(row.get("publication_year")),
                venue=venue if isinstance(venue, str) else None,
                doi=doi,
                repository_doi=repository_doi,
                url=landing_page
                if isinstance(landing_page, str)
                else row.get("id")
                if isinstance(row.get("id"), str)
                else None,
                citation_count=citation_count,
                citation_count_source="openalex" if citation_count is not None else None,
                citation_count_as_of=date.today() if citation_count is not None else None,
                publication_status=publication_status,
                status_source="openalex" if publication_status != "unknown" else None,
                status_as_of=date.today() if publication_status != "unknown" else None,
                source="openalex",
            )
        )
    return papers


def _parse_citation_count(value: Any) -> int | None:
    """Preserve a reported zero while keeping absent/invalid counts unknown."""

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return int(value)


def _classify_doi(value: Any) -> tuple[str | None, str | None]:
    """Separate known repository DOI namespaces from publication DOIs."""

    if not isinstance(value, str):
        return None, None
    normalized = normalize_doi(value)
    if normalized is None:
        return None, None
    if normalized.startswith(("10.48550/arxiv.", "10.5281/zenodo.")):
        return None, normalized
    return value, None


def _arxiv_atom_status(*, title: str, comment: str | None) -> PublicationStatus:
    status_text = " ".join(value for value in (title, comment) if value).casefold()
    if re.search(r"\b(?:retracted|retraction)\b", status_text):
        return "retracted"
    if re.search(r"\b(?:withdrawn|withdrawal)\b", status_text):
        return "withdrawn"
    return "preprint"


def _parse_arxiv_abs_status(text: str) -> PublicationStatus | None:
    status_text = re.sub(r"<[^>]+>", " ", text).casefold()
    if re.search(
        r"\b(?:this\s+)?(?:paper|submission|article|manuscript)\s+"
        r"(?:has\s+been\s+|was\s+)?retracted\b|\(\s*retracted\s*\)",
        status_text,
    ):
        return "retracted"
    if re.search(
        r"\b(?:this\s+)?(?:paper|submission|article|manuscript)\s+"
        r"(?:has\s+been\s+|was\s+)?withdrawn\b|\(\s*withdrawn\s*\)",
        status_text,
    ):
        return "withdrawn"
    return None


def _openalex_publication_status(row: dict[str, Any]) -> PublicationStatus:
    if row.get("is_retracted") is True:
        return "retracted"
    work_type = row.get("type")
    if work_type == "preprint":
        return "preprint"
    if isinstance(work_type, str) and work_type:
        return "published"
    return "unknown"


def _arxiv_repository_doi(url: str | None) -> str | None:
    """Derive the DataCite repository DOI from a canonical arXiv entry URL."""

    if url is None:
        return None
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc.casefold() not in {"arxiv.org", "www.arxiv.org", "export.arxiv.org"}:
        return None
    path = urllib.parse.unquote(parsed.path)
    identifier: str | None = None
    for prefix in ("/abs/", "/pdf/"):
        if path.startswith(prefix):
            identifier = path.removeprefix(prefix).removesuffix(".pdf")
            break
    if identifier is None:
        return None
    identifier = re.sub(r"v\d+$", "", identifier, flags=re.IGNORECASE)
    if not (
        re.fullmatch(r"\d{4}\.\d{4,5}", identifier)
        or re.fullmatch(r"[A-Za-z][A-Za-z0-9._-]*/\d{7}", identifier)
    ):
        return None
    return f"10.48550/arXiv.{identifier}"


def _openalex_authors(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    authors: list[str] = []
    for authorship in value:
        if not isinstance(authorship, dict):
            continue
        author = authorship.get("author")
        if isinstance(author, dict) and isinstance(author.get("display_name"), str):
            authors.append(author["display_name"])
    return authors


def _openalex_abstract(value: Any) -> str | None:
    if not isinstance(value, dict) or not value:
        return None
    positions: dict[int, str] = {}
    for token, raw_indexes in value.items():
        if not isinstance(token, str) or not isinstance(raw_indexes, list):
            continue
        for raw_index in raw_indexes:
            if isinstance(raw_index, int):
                positions[raw_index] = token
    if not positions:
        return None
    return " ".join(positions[index] for index in sorted(positions))


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
