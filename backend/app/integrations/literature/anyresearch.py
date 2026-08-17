"""AnySearch 学术域 Provider（用户称为「Any-research」）。

协议：POST https://api.anysearch.com/mcp，JSON-RPC 2.0 `tools/call`，
tool = `search`，domain = `academic`，sub_domain = `academic.search`。
鉴权：`Authorization: Bearer <LITERATURE_ANYRESEARCH_API_KEY>`。
"""

from __future__ import annotations

import re

import httpx

from app.core.config import get_settings
from app.integrations.literature.base import PaperResult
from app.integrations.literature.registry import register

_DOI_URL_RE = re.compile(r"https?://doi\.org/(10\.\d{4,9}/[^\s)\]]+)", re.IGNORECASE)


@register
class AnyResearchProvider:
    name = "anyresearch"

    def __init__(self, base_url: str = "https://api.anysearch.com/mcp") -> None:
        self.base_url = base_url

    async def search(self, query: str, max_results: int = 20) -> list[PaperResult]:
        settings = get_settings()
        api_key = settings.literature_anyresearch_api_key
        headers = {
            "Content-Type": "application/json",
            "X-Anysearch-Client": "mcp/1.0.0",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "search",
                "arguments": {
                    "query": query,
                    "domain": "academic",
                    "sub_domain": "academic.search",
                    "max_results": min(max_results, 10),
                },
            },
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(self.base_url, json=payload, headers=headers)
            response.raise_for_status()
        return self._parse(response.json())

    def _parse(self, payload: dict) -> list[PaperResult]:
        result = payload.get("result") or {}
        if result.get("isError"):
            raise RuntimeError(f"AnySearch 返回错误：{result.get('content')}")
        text = "\n".join(
            (block.get("text") or "") for block in (result.get("content") or [])
        ).strip()
        return self._parse_markdown(text)

    @staticmethod
    def _parse_markdown(text: str) -> list[PaperResult]:
        results: list[PaperResult] = []
        current_title: str | None = None
        current_url: str | None = None
        abstract_parts: list[str] = []

        def flush() -> None:
            nonlocal current_title, current_url, abstract_parts
            if current_title:
                doi = None
                if current_url:
                    match = _DOI_URL_RE.search(current_url)
                    if match:
                        doi = match.group(1)
                results.append(
                    PaperResult(
                        title=current_title,
                        doi=doi,
                        publication_year=None,
                        venue=None,
                        abstract=" ".join(abstract_parts).strip() or None,
                        external_id=current_url or doi,
                        source="anyresearch",
                    )
                )
            current_title, current_url, abstract_parts = None, None, []

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if line.startswith("### "):
                flush()
                heading = line[4:].strip()
                # 形如 "### 1. Title" → 去掉序号前缀
                heading = re.sub(r"^\d+\.\s*", "", heading)
                current_title = heading
                continue
            if current_title is None:
                continue
            if line.startswith("- **URL**:"):
                current_url = line.split(":", 1)[1].strip() or None
                continue
            if line.startswith("- "):
                abstract_parts.append(line[2:].strip())
        flush()
        return results
