"""OpenAlex literature provider (REST to api.openalex.org/works).

OpenAlex 本身不需要 API Key（加入 `mailto` 即进入 polite pool，更稳更快）；
如配置了 `LITERATURE_OPENALEX_API_KEY`，则一并作为 `api_key` 透传（前向兼容）。
"""

from __future__ import annotations

import httpx

from app.core.config import get_settings
from app.integrations.literature._util import reconstruct_inverted_index
from app.integrations.literature.base import PaperResult
from app.integrations.literature.registry import register


@register
class OpenAlexProvider:
    name = "openalex"

    def __init__(self, base_url: str = "https://api.openalex.org/works") -> None:
        self.base_url = base_url

    async def search(self, query: str, max_results: int = 20) -> list[PaperResult]:
        settings = get_settings()
        params: dict[str, object] = {
            "search": query,
            "per-page": min(max_results, 100),
            "mailto": settings.literature_mailto or "research@airesearcher.local",
        }
        if settings.literature_openalex_api_key:
            params["api_key"] = settings.literature_openalex_api_key
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(self.base_url, params=params)
            response.raise_for_status()
        return self._parse(response.json())

    def _parse(self, payload: dict) -> list[PaperResult]:
        results: list[PaperResult] = []
        for work in payload.get("results", []):
            title = (work.get("title") or work.get("display_name") or "").strip()
            if not title:
                continue
            venue = None
            primary_location = work.get("primary_location") or {}
            source = primary_location.get("source") or {}
            if source.get("display_name"):
                venue = source["display_name"]
            results.append(
                PaperResult(
                    title=title,
                    doi=work.get("doi"),
                    publication_year=work.get("publication_year"),
                    venue=venue,
                    abstract=reconstruct_inverted_index(work.get("abstract_inverted_index")),
                    external_id=work.get("id"),
                    source=self.name,
                )
            )
        return results
