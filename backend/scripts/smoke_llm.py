"""LLM provider smoke test (real call)."""

from __future__ import annotations

import asyncio

from app.integrations.llm.base import get_provider


async def main() -> None:
    provider = get_provider("qwen-dashscope-compatible")
    response = await provider.complete(
        "用一句话回答：什么是蛋白质-小分子相互作用预测？"
    )
    print("content =", response.content[:300])
    print("usage =", response.usage)


if __name__ == "__main__":
    asyncio.run(main())
