"""Crossref literature provider（REST to api.crossref.org/works）。

Crossref 公开 API 无需 Key；加 `mailto` 进入 polite pool。若配置了
`LITERATURE_CROSSREF_API_KEY`，作为 Plus 令牌走 `Authorization`（可选）。
"""

from __future__ import annotations

import httpx

from app.core.config import get_settings
from app.integrations.literature._util import strip_tags
from app.integrations.literature.base import PaperResult
from app.integrations.literature.registry import register


@register
class CrossrefProvider:
    name = "crossref"

    def __init__(self, base_url: str = "https://api.crossref.org/works") -> None:
        self.base_url = base_url

    async def search(self, query: str, max_results: int = 20) -> list[PaperResult]:
        settings = get_settings()
        params: dict[str, object] = {
            "query": query,
            "rows": min(max_results, 100),
            "mailto": settings.literature_mailto or "research@airesearcher.local",
        }
        headers: dict[str, str] = {}
        if settings.literature_crossref_api_key:
            headers["Authorization"] = f"Bearer {settings.literature_crossref_api_key}"
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(self.base_url, params=params, headers=headers)
            response.raise_for_status()
        return self._parse(response.json())

    def _parse(self, payload: dict) -> list[PaperResult]:
        results: list[PaperResult] = []
        for item in (payload.get("message") or {}).get("items", []):
            titles = item.get("title") or []
            title = (titles[0] if titles else "").strip()
            if not title:
                continue
            venue = None
            containers = item.get("container-title") or []
            if containers:
                venue = containers[0]
            abstract = item.get("abstract")
            abstract = strip_tags(abstract) if abstract else None
            year = self._year(item)
            results.append(
                PaperResult(
                    title=title,
                    doi=item.get("DOI"),
                    publication_year=year,
                    venue=venue,
                    abstract=abstract,
                    external_id=item.get("DOI"),
                    source=self.name,
                )
            )
        return results

    @staticmethod
    def _year(item: dict) -> int | None:
        for key in ("published-print", "published-online", "issued", "created"):
            value = item.get(key) or {}
            parts = value.get("date-parts") or []
            if parts and parts[0] and parts[0][0]:
                return int(parts[0][0])
        return None
