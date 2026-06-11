"""Filesystem cache for literature retrieval responses."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .models import AcademicPaper


class RetrievalCacheRecord(BaseModel):
    """Serialized cache payload for one retrieval request."""

    model_config = ConfigDict(extra="forbid")

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    papers: list[AcademicPaper]


def retrieval_cache_key(
    *,
    query: str,
    source: str,
    page: int,
    limit: int,
    config: dict[str, Any] | None = None,
) -> str:
    payload = {
        "config": config or {},
        "limit": limit,
        "page": page,
        "query": query,
        "source": source,
    }
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class RetrievalCache:
    """Cache successful literature retrievals for a bounded time window."""

    def __init__(self, root: Path | str, *, ttl_hours: int = 24) -> None:
        self.root = Path(root)
        self.ttl = timedelta(hours=ttl_hours)

    def get(self, key: str, *, now: datetime | None = None) -> list[AcademicPaper] | None:
        path = self._path_for_key(key)
        if not path.exists():
            return None

        record = RetrievalCacheRecord.model_validate_json(path.read_text(encoding="utf-8"))
        timestamp = now or datetime.now(timezone.utc)
        if timestamp - record.created_at > self.ttl:
            return None
        return record.papers

    def set(
        self,
        key: str,
        papers: list[AcademicPaper],
        *,
        now: datetime | None = None,
    ) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        record = RetrievalCacheRecord(
            created_at=now or datetime.now(timezone.utc),
            papers=papers,
        )
        path = self._path_for_key(key)
        path.write_text(record.model_dump_json(), encoding="utf-8")
        return path

    def get_or_fetch(
        self,
        *,
        query: str,
        source: str,
        page: int,
        limit: int,
        config: dict[str, Any] | None,
        fetcher: Callable[[], list[AcademicPaper]],
        now: datetime | None = None,
    ) -> list[AcademicPaper]:
        key = retrieval_cache_key(
            query=query,
            source=source,
            page=page,
            limit=limit,
            config=config,
        )
        cached = self.get(key, now=now)
        if cached is not None:
            return cached

        papers = fetcher()
        self.set(key, papers, now=now)
        return papers

    def _path_for_key(self, key: str) -> Path:
        return self.root / f"{key}.json"
