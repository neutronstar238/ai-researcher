"""Semantic Scholar literature provider（Graph API `/paper/search`，见用户提供的 swagger.json）。

官方限流：1 req/s（跨所有端点累计）。这里用进程内异步锁做 1 req/s 节流，
并对 429 做指数退避重试 + 尊重 `Retry-After`。
"""

from __future__ import annotations

import asyncio
import time

import httpx

from app.core.config import get_settings
from app.integrations.literature.base import PaperResult
from app.integrations.literature.registry import register

# 进程内 1 req/s 节流（跨实例共享）。
_rate_lock = asyncio.Lock()
_last_request_at = 0.0


async def _throttle() -> None:
    global _last_request_at
    async with _rate_lock:
        wait = 1.0 - (time.monotonic() - _last_request_at)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request_at = time.monotonic()


@register
class SemanticScholarProvider:
    name = "semantic_scholar"

    def __init__(self, base_url: str = "https://api.semanticscholar.org/graph/v1/paper/search") -> None:
        self.base_url = base_url

    async def search(self, query: str, max_results: int = 20) -> list[PaperResult]:
        settings = get_settings()
        headers = {"User-Agent": "ai-researcher/1.0"}
        if settings.literature_semantic_scholar_api_key:
            headers["x-api-key"] = settings.literature_semantic_scholar_api_key
        params = {
            "query": query,
            "limit": min(max_results, 100),
            "fields": "title,abstract,year,venue,externalIds,url",
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            await _throttle()
            for attempt in range(4):
                response = await client.get(self.base_url, params=params, headers=headers)
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    wait = float(retry_after) if retry_after else min(2 ** attempt, 8.0)
                    await asyncio.sleep(wait)
                    continue
                response.raise_for_status()
                return self._parse(response.json())
        raise httpx.HTTPStatusError(
            "Semantic Scholar 连续 429（限流），请稍后重试或配置 API Key",
            request=response.request,
            response=response,
        )

    def _parse(self, payload: dict) -> list[PaperResult]:
        results: list[PaperResult] = []
        for paper in payload.get("data", []):
            title = (paper.get("title") or "").strip()
            if not title:
                continue
            external_ids = paper.get("externalIds") or {}
            doi = external_ids.get("DOI")
            results.append(
                PaperResult(
                    title=title,
                    doi=doi,
                    publication_year=paper.get("year"),
                    venue=paper.get("venue"),
                    abstract=paper.get("abstract"),
                    external_id=paper.get("paperId") or external_ids.get("CorpusId"),
                    source=self.name,
                )
            )
        return results
