"""Rate limiter unit test (real Redis)."""

from __future__ import annotations

import asyncio
import time
import uuid

from app.core.rate_limit import RateLimiter


def test_fixed_window_limits() -> None:
    async def run() -> list[bool]:
        limiter = RateLimiter(window_seconds=60)
        key = f"test:{int(time.time())}:{uuid.uuid4().hex[:8]}"
        return [await limiter.allow(key, 3) for _ in range(5)]

    results = asyncio.run(run())
    assert results[:3] == [True, True, True]
    assert results[3:] == [False, False]


def test_distinct_keys_do_not_interfere() -> None:
    async def run() -> bool:
        limiter = RateLimiter(window_seconds=60)
        a = f"test:a:{uuid.uuid4().hex[:8]}"
        b = f"test:b:{uuid.uuid4().hex[:8]}"
        await limiter.allow(a, 1)
        await limiter.allow(a, 1)
        return await limiter.allow(b, 1)

    assert asyncio.run(run()) is True
