"""多文献源冒烟测试：逐个真实调用，验证 Key 与解析。"""

from __future__ import annotations

import asyncio

from app.integrations.literature.registry import get_provider

CASES = [
    ("arxiv", "protein ligand binding affinity"),
    ("openalex", "protein ligand binding affinity"),
    ("semantic_scholar", "protein ligand binding affinity"),
    ("crossref", "protein ligand binding affinity"),
    ("pubmed", "covid vaccine efficacy"),          # 医药 → 应命中
    ("pubmed", "transformer attention mechanism"),  # 非医药 → 应空
    ("anyresearch", "protein ligand binding affinity"),
]


async def main() -> None:
    for name, query in CASES:
        try:
            provider = get_provider(name)
            results = await provider.search(query, max_results=5)
            first = results[0].title[:70] if results else "(none)"
            print(f"[{name:>16}] query={query[:38]:<38} hits={len(results):<3} first={first}")
        except Exception as exc:  # noqa: BLE001
            print(f"[{name:>16}] query={query[:38]:<38} ERROR={type(exc).__name__}: {str(exc)[:120]}")


if __name__ == "__main__":
    asyncio.run(main())
