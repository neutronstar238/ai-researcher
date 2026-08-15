"""Official, source-bound model context capabilities.

The context limit is deliberately not a user-tuned number.  It is parsed from
the configured provider's official model page, stored together with the exact
source bytes, and reused from a verified local cache when the page is briefly
unavailable.  The policy ratio (80 percent) is separate from the provider fact.
"""

from __future__ import annotations

import hashlib
import html
import json
import math
import os
import re
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from autoresearch.kernel.contracts import KernelContract, Sha256, canonical_json, canonical_sha256

OFFICIAL_CONTEXT_COMPRESSION_RATIO = 0.8
OFFICIAL_COMPLETION_TOKEN_OVERRUN_ALLOWANCE: Literal[10] = 10
_PARSER_VERSION: Literal["aliyun-model-page-v1"] = "aliyun-model-page-v1"
_OFFICIAL_HOST = "help.aliyun.com"
_DEFAULT_CACHE_TTL = timedelta(hours=24)
_MODEL_PAGE = "https://help.aliyun.com/zh/model-studio/qwen3-7-max"
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_META_LAST_MODIFIED = re.compile(r'<meta\s+name="last-modified"\s+content="([^"]+)"', re.IGNORECASE)
_PAGE_PROPS_MARKER = "window.__ICE_PAGE_PROPS__="

OfficialPageFetcher = Callable[[str], tuple[bytes, str]]


class OfficialModelCapabilityError(RuntimeError):
    """Raised when an official model limit cannot be established."""


class _TableCollector(HTMLParser):
    """Collect table rows without depending on third-party HTML libraries."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell_parts: list[str] | None = None

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table" and self._table is None:
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell_parts = []

    def handle_data(self, data: str) -> None:
        if self._cell_parts is not None:
            self._cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell_parts is not None:
            assert self._row is not None
            self._row.append(" ".join("".join(self._cell_parts).split()))
            self._cell_parts = None
        elif tag == "tr" and self._row is not None:
            assert self._table is not None
            if self._row:
                self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None


class OfficialModelCapability(KernelContract):
    """One exact capability snapshot parsed from an official provider page."""

    schema_version: Literal["official-model-capability-v1"] = "official-model-capability-v1"
    provider: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    official_source_url: str = Field(min_length=1)
    official_source_last_modified: str = Field(min_length=1)
    fetched_at: datetime
    source_sha256: Sha256
    source_size_bytes: int = Field(ge=1)
    parser_version: Literal["aliyun-model-page-v1"] = _PARSER_VERSION
    context_window_tokens: int = Field(ge=1)
    maximum_input_tokens: int = Field(ge=1)
    maximum_output_tokens: int = Field(ge=1)
    maximum_input_tokens_thinking: int = Field(ge=1)
    maximum_output_tokens_thinking: int = Field(ge=1)
    maximum_reasoning_tokens: int = Field(ge=1)
    capability_hash: Sha256

    @field_validator("fetched_at")
    @classmethod
    def _utc_fetched_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("fetched_at must be timezone-aware")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _verify_capability(self) -> OfficialModelCapability:
        parsed = urllib.parse.urlsplit(self.official_source_url)
        if parsed.scheme != "https" or parsed.hostname != _OFFICIAL_HOST:
            raise ValueError("model capability source is not the official HTTPS host")
        if self.maximum_input_tokens > self.context_window_tokens:
            raise ValueError("maximum input exceeds the official context window")
        if self.maximum_input_tokens_thinking > self.context_window_tokens:
            raise ValueError("thinking input exceeds the official context window")
        if self.maximum_output_tokens > self.context_window_tokens:
            raise ValueError("maximum output exceeds the official context window")
        if self.maximum_output_tokens_thinking > self.context_window_tokens:
            raise ValueError("thinking output exceeds the official context window")
        if self.maximum_reasoning_tokens > self.context_window_tokens:
            raise ValueError("maximum reasoning exceeds the official context window")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"capability_hash"}))
        if self.capability_hash != expected:
            raise ValueError("official model capability hash mismatch")
        return self


class ModelContextBudget(KernelContract):
    """80-percent compression trigger derived from an official capability."""

    schema_version: Literal[
        "model-context-budget-v1",
        "model-context-budget-v2",
    ] = "model-context-budget-v2"
    capability_hash: Sha256
    model_name: str = Field(min_length=1)
    official_context_window_tokens: int = Field(ge=1)
    compression_trigger_ratio: float = Field(default=OFFICIAL_CONTEXT_COMPRESSION_RATIO)
    compression_trigger_tokens: int = Field(ge=1)
    mode_maximum_input_tokens: int = Field(ge=1)
    hard_input_limit_tokens: int = Field(ge=1)
    requested_output_tokens: int = Field(ge=1)
    completion_token_overrun_allowance_tokens: Literal[10] = (
        OFFICIAL_COMPLETION_TOKEN_OVERRUN_ALLOWANCE
    )
    official_maximum_reasoning_tokens: int = Field(ge=1)
    thinking_mode: Literal["enabled", "disabled"]
    thinking_budget_tokens: int | None = Field(default=None, ge=1)
    budget_hash: Sha256

    @model_validator(mode="after")
    def _verify_budget(self) -> ModelContextBudget:
        if self.compression_trigger_ratio != OFFICIAL_CONTEXT_COMPRESSION_RATIO:
            raise ValueError("context compression trigger ratio must remain exactly 0.8")
        expected_trigger = math.floor(
            self.official_context_window_tokens * self.compression_trigger_ratio
        )
        if self.compression_trigger_tokens != expected_trigger:
            raise ValueError("compression trigger is not exactly 80% of official context")
        reasoning_reserve = (
            self.thinking_budget_tokens if self.schema_version == "model-context-budget-v2" else 0
        )
        expected_hard_input = min(
            self.mode_maximum_input_tokens,
            self.official_context_window_tokens
            - self.requested_output_tokens
            - (reasoning_reserve or 0)
            - self.completion_token_overrun_allowance_tokens,
        )
        if self.hard_input_limit_tokens != expected_hard_input:
            raise ValueError("hard input limit does not reserve answer and reasoning budgets")
        if self.compression_trigger_tokens >= self.hard_input_limit_tokens:
            raise ValueError("official input limit is below the requested 80% trigger")
        if self.thinking_mode == "enabled":
            if self.thinking_budget_tokens is None:
                raise ValueError("enabled thinking requires an explicit thinking budget")
            if self.thinking_budget_tokens > self.official_maximum_reasoning_tokens:
                raise ValueError("thinking budget exceeds the official maximum reasoning length")
        elif self.thinking_budget_tokens is not None:
            raise ValueError("disabled thinking cannot retain a thinking budget")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"budget_hash"}))
        if self.budget_hash != expected:
            raise ValueError("model context budget hash mismatch")
        return self


def official_model_source_url(*, provider: str, model_name: str) -> str:
    """Resolve an official page without embedding any model limit value."""

    normalized_provider = provider.strip().lower()
    normalized_model = model_name.strip().lower()
    if normalized_provider in {"qwen-dashscope", "dashscope", "aliyun-bailian"} and (
        normalized_model == "qwen3.7-max" or normalized_model.startswith("qwen3.7-max-")
    ):
        return _MODEL_PAGE
    raise OfficialModelCapabilityError(
        "no official capability source is registered for "
        f"provider={provider!r}, model={model_name!r}; refusing a guessed limit"
    )


def parse_official_model_capability(
    source_bytes: bytes,
    *,
    provider: str,
    model_name: str,
    source_url: str,
    fetched_at: datetime,
) -> OfficialModelCapability:
    """Parse the current-model context table from exact Aliyun help-page bytes."""

    if not source_bytes:
        raise OfficialModelCapabilityError("official capability page is empty")
    try:
        page = source_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise OfficialModelCapabilityError("official capability page is not UTF-8") from exc
    parsed_url = urllib.parse.urlsplit(source_url)
    if parsed_url.scheme != "https" or parsed_url.hostname != _OFFICIAL_HOST:
        raise OfficialModelCapabilityError("capability page is not on help.aliyun.com")
    marker_index = page.find(_PAGE_PROPS_MARKER)
    if marker_index < 0:
        raise OfficialModelCapabilityError("official page lacks its structured document payload")
    json_start = marker_index + len(_PAGE_PROPS_MARKER)
    try:
        props, _end = json.JSONDecoder().raw_decode(page[json_start:])
        document = props["docDetailData"]["storeData"]["data"]
        title = str(document["title"])
        content = str(document["content"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise OfficialModelCapabilityError(
            "official page structured document payload is invalid"
        ) from exc
    normalized_model = model_name.strip().lower()
    if normalized_model == "qwen3.7-max":
        expected_title = "qwen3.7-max"
    elif normalized_model.startswith("qwen3.7-max-"):
        expected_title = normalized_model
    else:
        raise OfficialModelCapabilityError("the parser only accepts qwen3.7-max family pages")
    if expected_title not in title.lower() and expected_title not in content.lower():
        raise OfficialModelCapabilityError("official page does not name the configured model")

    # The page may contain several historical snapshot sections.  The default model's
    # table is before the first h3 snapshot heading.  Labels have occasionally been
    # mojibaked by the site renderer, so select the structurally valid six-value table
    # instead of trusting translated label bytes.  Values still come solely from the
    # official page and are subjected to cross-field invariants below.
    default_section = content.split("<h3", 1)[0]
    collector = _TableCollector()
    collector.feed(default_section)
    limits: tuple[int, int, int, int, int, int] | None = None
    for table in collector.tables:
        numeric_rows: list[list[int]] = []
        for row in table:
            values = [_parse_integer_cell(cell) for cell in row]
            row_numbers = [value for value in values if value is not None]
            if row_numbers:
                numeric_rows.append(row_numbers)
        if len(numeric_rows) < 3 or any(len(row) < 2 for row in numeric_rows[:2]):
            continue
        first, second, third = numeric_rows[0], numeric_rows[1], numeric_rows[2]
        if len(third) < 2:
            continue
        maximum_input, maximum_output = first[:2]
        context_window, maximum_input_thinking = second[:2]
        maximum_output_thinking, maximum_reasoning = third[:2]
        if (
            context_window >= maximum_input >= 4_096
            and context_window >= maximum_input_thinking >= 4_096
            and context_window >= maximum_output >= 1_024
            and context_window >= maximum_output_thinking >= 1_024
            and context_window >= maximum_reasoning >= 1_024
            and maximum_input > maximum_output
            and maximum_input_thinking > maximum_output_thinking
        ):
            limits = (
                maximum_input,
                maximum_output,
                context_window,
                maximum_input_thinking,
                maximum_output_thinking,
                maximum_reasoning,
            )
            break
    if limits is None:
        raise OfficialModelCapabilityError("official context-limit table was not found")

    modified_match = _META_LAST_MODIFIED.search(page)
    last_modified = (
        html.unescape(modified_match.group(1))
        if modified_match is not None
        else str(document.get("lastModifiedTime", "unknown"))
    )
    (
        maximum_input,
        maximum_output,
        context_window,
        input_thinking,
        output_thinking,
        maximum_reasoning,
    ) = limits
    payload = {
        "schema_version": "official-model-capability-v1",
        "provider": provider,
        "model_name": model_name,
        "official_source_url": source_url,
        "official_source_last_modified": last_modified,
        "fetched_at": fetched_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "source_size_bytes": len(source_bytes),
        "parser_version": _PARSER_VERSION,
        "context_window_tokens": context_window,
        "maximum_input_tokens": maximum_input,
        "maximum_output_tokens": maximum_output,
        "maximum_input_tokens_thinking": input_thinking,
        "maximum_output_tokens_thinking": output_thinking,
        "maximum_reasoning_tokens": maximum_reasoning,
    }
    payload["capability_hash"] = canonical_sha256(payload)
    return OfficialModelCapability.model_validate(payload)


def load_official_model_capability(
    *,
    provider: str,
    model_name: str,
    cache_dir: Path | str = Path(".cache/autoresearch/model-capabilities"),
    force_refresh: bool = False,
    fetcher: OfficialPageFetcher | None = None,
    clock: datetime | None = None,
    cache_ttl: timedelta = _DEFAULT_CACHE_TTL,
) -> OfficialModelCapability:
    """Load a verified recent cache or fetch and snapshot the official page."""

    now = (clock or datetime.now(timezone.utc)).astimezone(timezone.utc)
    root = Path(cache_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^a-z0-9_.-]+", "-", model_name.strip().lower()).strip("-")
    if not safe_name:
        raise OfficialModelCapabilityError("model name cannot form a cache key")
    pointer = root / f"{safe_name}.json"
    cached: OfficialModelCapability | None = None
    if not force_refresh and pointer.is_file():
        try:
            cached = _load_cached_capability(pointer, root=root)
        except OfficialModelCapabilityError:
            # Capability schemas follow the official page.  A previously valid
            # cache can therefore become incomplete when a newly frozen field is
            # added; refresh it instead of treating the stale pointer as current.
            if not _is_legacy_cache_without_reasoning_limit(pointer):
                raise
            cached = None
        if cached is not None and now - cached.fetched_at <= cache_ttl:
            return cached

    source_url = official_model_source_url(provider=provider, model_name=model_name)
    try:
        source_bytes, final_url = (fetcher or _fetch_official_page)(source_url)
        capability = parse_official_model_capability(
            source_bytes,
            provider=provider,
            model_name=model_name,
            source_url=final_url,
            fetched_at=now,
        )
    except (OSError, TimeoutError, OfficialModelCapabilityError) as exc:
        if cached is not None:
            return cached
        raise OfficialModelCapabilityError(
            "official model capability is unavailable and no verified cache exists"
        ) from exc

    source_path = root / f"source-{capability.source_sha256}.html"
    _write_once_bytes(source_path, source_bytes)
    if hashlib.sha256(source_path.read_bytes()).hexdigest() != capability.source_sha256:
        raise OfficialModelCapabilityError("cached official source bytes changed")
    _atomic_write(pointer, canonical_json(capability).encode("utf-8") + b"\n")
    return _load_cached_capability(pointer, root=root)


def build_model_context_budget(
    capability: OfficialModelCapability,
    *,
    thinking_mode: Literal["enabled", "disabled"],
    thinking_budget: int | None,
    requested_output_tokens: int,
) -> ModelContextBudget:
    """Derive the user's 80-percent trigger from the official page snapshot."""

    if requested_output_tokens < 1:
        raise OfficialModelCapabilityError("requested output tokens must be positive")
    official_output = (
        capability.maximum_output_tokens_thinking
        if thinking_mode == "enabled"
        else capability.maximum_output_tokens
    )
    if requested_output_tokens > official_output:
        raise OfficialModelCapabilityError("requested output exceeds the official model limit")
    if thinking_mode == "enabled":
        if thinking_budget is None or thinking_budget < 1:
            raise OfficialModelCapabilityError(
                "enabled thinking requires a positive thinking budget"
            )
        if thinking_budget > capability.maximum_reasoning_tokens:
            raise OfficialModelCapabilityError(
                "thinking budget exceeds the official maximum reasoning length"
            )
    elif thinking_budget is not None:
        raise OfficialModelCapabilityError(
            "thinking budget must be absent when thinking is disabled"
        )
    mode_maximum_input = (
        capability.maximum_input_tokens_thinking
        if thinking_mode == "enabled"
        else capability.maximum_input_tokens
    )
    context_reserved_input = (
        capability.context_window_tokens
        - requested_output_tokens
        - (thinking_budget or 0)
        - OFFICIAL_COMPLETION_TOKEN_OVERRUN_ALLOWANCE
    )
    if context_reserved_input < 1:
        raise OfficialModelCapabilityError(
            "requested output leaves no input capacity after the provider overrun allowance"
        )
    hard_input = min(mode_maximum_input, context_reserved_input)
    payload = {
        "schema_version": "model-context-budget-v2",
        "capability_hash": capability.capability_hash,
        "model_name": capability.model_name,
        "official_context_window_tokens": capability.context_window_tokens,
        "compression_trigger_ratio": OFFICIAL_CONTEXT_COMPRESSION_RATIO,
        "compression_trigger_tokens": math.floor(
            capability.context_window_tokens * OFFICIAL_CONTEXT_COMPRESSION_RATIO
        ),
        "mode_maximum_input_tokens": mode_maximum_input,
        "hard_input_limit_tokens": hard_input,
        "requested_output_tokens": requested_output_tokens,
        "completion_token_overrun_allowance_tokens": (OFFICIAL_COMPLETION_TOKEN_OVERRUN_ALLOWANCE),
        "official_maximum_reasoning_tokens": capability.maximum_reasoning_tokens,
        "thinking_mode": thinking_mode,
        "thinking_budget_tokens": thinking_budget,
    }
    payload["budget_hash"] = canonical_sha256(payload)
    return ModelContextBudget.model_validate(payload)


def _parse_integer_cell(value: str) -> int | None:
    normalized = value.replace(",", "").strip()
    return int(normalized) if re.fullmatch(r"[0-9]+", normalized) else None


def _fetch_official_page(url: str) -> tuple[bytes, str]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "AutoResearch-OfficialCapability/1.0"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        final_url = str(response.geturl())
        parsed = urllib.parse.urlsplit(final_url)
        if parsed.scheme != "https" or parsed.hostname != _OFFICIAL_HOST:
            raise OfficialModelCapabilityError("official page redirected outside its trust host")
        content_type = str(response.headers.get("Content-Type", "")).lower()
        if "text/html" not in content_type:
            raise OfficialModelCapabilityError("official capability source is not HTML")
        return response.read(), final_url


def _load_cached_capability(path: Path, *, root: Path) -> OfficialModelCapability:
    try:
        capability = OfficialModelCapability.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise OfficialModelCapabilityError("cached model capability is invalid") from exc
    source_path = root / f"source-{capability.source_sha256}.html"
    if not source_path.is_file():
        raise OfficialModelCapabilityError("cached official source bytes are missing")
    source_bytes = source_path.read_bytes()
    if (
        len(source_bytes) != capability.source_size_bytes
        or hashlib.sha256(source_bytes).hexdigest() != capability.source_sha256
    ):
        raise OfficialModelCapabilityError("cached official source bytes are corrupt")
    replayed = parse_official_model_capability(
        source_bytes,
        provider=capability.provider,
        model_name=capability.model_name,
        source_url=capability.official_source_url,
        fetched_at=capability.fetched_at,
    )
    if replayed != capability:
        raise OfficialModelCapabilityError("cached capability differs from source replay")
    return capability


def _is_legacy_cache_without_reasoning_limit(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return (
        isinstance(payload, dict)
        and payload.get("schema_version") == "official-model-capability-v1"
        and "maximum_reasoning_tokens" not in payload
    )


def _write_once_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if path.read_bytes() != payload:
            raise OfficialModelCapabilityError(
                "official source hash path has different bytes"
            ) from None
        return
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _atomic_write(path: Path, payload: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


__all__ = [
    "ModelContextBudget",
    "OFFICIAL_COMPLETION_TOKEN_OVERRUN_ALLOWANCE",
    "OFFICIAL_CONTEXT_COMPRESSION_RATIO",
    "OfficialModelCapability",
    "OfficialModelCapabilityError",
    "build_model_context_budget",
    "load_official_model_capability",
    "official_model_source_url",
    "parse_official_model_capability",
]
