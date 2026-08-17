"""arXiv literature provider (real HTTP to the arXiv Atom API)."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import httpx

from app.integrations.literature.base import PaperResult
from app.integrations.literature.registry import register

_ARXIV_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


@register
class ArxivProvider:
    name = "arxiv"

    def __init__(self, base_url: str = "https://export.arxiv.org/api/query") -> None:
        self.base_url = base_url

    async def search(self, query: str, max_results: int = 20) -> list[PaperResult]:
        params = {"search_query": f"all:{query}", "start": 0, "max_results": max_results}
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(self.base_url, params=params)
            response.raise_for_status()
        return self._parse(response.text)

    def _parse(self, xml_text: str) -> list[PaperResult]:
        root = ET.fromstring(xml_text)
        results: list[PaperResult] = []
        for entry in root.findall("atom:entry", _ARXIV_NS):
            title = (entry.findtext("atom:title", default="", namespaces=_ARXIV_NS) or "").strip()
            if not title:
                continue
            abstract = (entry.findtext("atom:summary", default="", namespaces=_ARXIV_NS) or "").strip()
            external_id = (entry.findtext("atom:id", default="", namespaces=_ARXIV_NS) or "").strip()
            doi = entry.findtext("arxiv:doi", default=None, namespaces=_ARXIV_NS)
            published = entry.findtext("atom:published", default="", namespaces=_ARXIV_NS) or ""
            year = int(published[:4]) if len(published) >= 4 else None
            results.append(
                PaperResult(
                    title=title,
                    abstract=abstract,
                    external_id=external_id,
                    doi=doi,
                    publication_year=year,
                    source=self.name,
                )
            )
        return results


# 向后兼容：历史上 `get_provider`/`PROVIDERS` 从 arxiv 模块导出（§10.6 注册表现已集中到 registry）。
from app.integrations.literature.registry import PROVIDERS, get_provider  # noqa: E402, F401
