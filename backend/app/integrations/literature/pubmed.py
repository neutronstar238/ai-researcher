"""PubMed literature provider (NCBI E-utilities)。

仅对医药相关问题生效：非医药 query 直接返回空结果（由服务层补 note）。
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import httpx

from app.core.config import get_settings
from app.integrations.literature._util import is_medical_query, strip_tags
from app.integrations.literature.base import PaperResult
from app.integrations.literature.registry import register

_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


@register
class PubmedProvider:
    name = "pubmed"

    def __init__(self, base_url: str = _BASE) -> None:
        self.base_url = base_url

    async def search(self, query: str, max_results: int = 20) -> list[PaperResult]:
        # 领域门控：PubMed 仅对医药相关问题生效（用户约束）。
        if not is_medical_query(query):
            return []
        settings = get_settings()
        api_key = settings.literature_pubmed_api_key
        async with httpx.AsyncClient(timeout=20.0) as client:
            # 若配置的 Key 被 NCBI 拒绝（400/401），降级为匿名访问。
            ids, effective_key = await self._esearch(client, query, max_results, api_key)
            if not ids:
                return []
            efetch_params: dict[str, str] = {"db": "pubmed", "id": ",".join(ids), "retmode": "xml"}
            if effective_key:
                efetch_params["api_key"] = effective_key
            efetch = await client.get(f"{self.base_url}/efetch.fcgi", params=efetch_params)
            efetch.raise_for_status()
        return self._parse(efetch.text)

    async def _esearch(
        self, client: httpx.AsyncClient, query: str, max_results: int, api_key: str | None
    ) -> tuple[list[str], str | None]:
        """esearch；返回 (idlist, 有效 key)。无效 Key 自动匿名降级，保证功能可用。"""
        for key in (api_key, None):
            params = {
                "db": "pubmed",
                "term": query,
                "retmax": min(max_results, 100),
                "retmode": "json",
            }
            if key:
                params["api_key"] = key
            response = await client.get(f"{self.base_url}/esearch.fcgi", params=params)
            if response.status_code in {400, 401} and key:
                continue  # 无效/过期 Key → 匿名降级
            response.raise_for_status()
            ids = (response.json().get("esearchresult") or {}).get("idlist") or []
            return ids, key
        return [], None

    def _parse(self, xml_text: str) -> list[PaperResult]:
        root = ET.fromstring(xml_text)
        results: list[PaperResult] = []
        for article in root.findall(".//PubmedArticle"):
            medline = article.find(".//MedlineCitation")
            if medline is None:
                continue
            title = (medline.findtext(".//Article/ArticleTitle", default="") or "").strip()
            if not title:
                continue
            # 摘要可能被拆成多个 AbstractText 段落。
            abstract_parts = [
                (node.text or "").strip()
                for node in medline.findall(".//Abstract/AbstractText")
                if node.text
            ]
            abstract = " ".join(abstract_parts).strip() or None
            journal = (medline.findtext(".//Article/Journal/Title", default="") or "").strip() or None
            year_text = (medline.findtext(".//Article/Journal/JournalIssue/PubDate/Year", default="") or "").strip()
            year = int(year_text) if year_text.isdigit() else None
            doi = None
            for node in medline.findall(".//ArticleIdList/ArticleId"):
                if node.get("IdType") == "doi":
                    doi = node.text or ""
                    break
            pmid = (medline.findtext(".//PMID", default="") or "").strip()
            abstract = strip_tags(abstract) if abstract else None
            results.append(
                PaperResult(
                    title=title,
                    doi=doi or None,
                    publication_year=year,
                    venue=journal,
                    abstract=abstract,
                    external_id=pmid or None,
                    source=self.name,
                )
            )
        return results
